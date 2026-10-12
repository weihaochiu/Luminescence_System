"""Production light integration, using fake serial devices only."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from shiboken6 import isValid

from qt_test_utils import ensure_qapplication
from test_gsp4h_controller import FakeDevice, FakeRegistry, READ_COMMANDS
from core.i18n import Language, configure_i18n, set_language
from gui.light_panel import LightPanel, LightSettingsDialog
from gui.light_service import LightService
from gui.main_window import MainWindow
from gui.el_matrix_hardware import ELMatrixHardwareAdapter
from gui.pixel_csv_postprocessor import verified_safe_shutdown
from gui.emergency_manager import EmergencyManager
from test_emergency_manager import FakeSMUControl, FakeRelayService
from test_close_safety import close_fixture, FakeCloseEvent
from tools.gsp4h_controller.settings import BrightnessStore
from tools.gsp4h_controller.worker import ControllerWorker


class LightIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def setUp(self):
        self.runtime = TemporaryDirectory()
        self.root = Path(self.runtime.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.registry = FakeRegistry()
        self.services = []
        self.widgets = []
        configure_i18n(self.settings)

    def tearDown(self):
        self.registry.release.set()
        for device in self.registry.devices.values():
            device.replies.clear()
            device.ignore.clear()
        for service in self.services:
            for transport in self.registry.transports:
                transport.fail_close = False
            self.assertTrue(service.shutdown())
        for widget in self.widgets:
            if isValid(widget):
                widget.close()
        self.app.processEvents()
        configure_i18n(None)
        self.runtime.cleanup()

    def service(self, *, legacy=None):
        worker = ControllerWorker(Event(), self.registry.make_transport, self.registry.ports)
        service = LightService(self.root / "light.json", self.settings,
                               worker=worker, legacy_path=legacy)
        service.SAFETY_TIMEOUT_MS = 2000
        self.services.append(service)
        return service

    def wait(self, predicate, seconds=3):
        deadline = monotonic() + seconds
        while not predicate() and monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(predicate())

    def connect(self, service):
        self.assertTrue(service.auto_connect())
        self.wait(lambda: not service.busy)
        self.assertTrue(service.state.ready)

    def test_auto_connect_only_reads_and_remembers_port(self):
        service = self.service()
        self.connect(service)
        self.assertTrue(all(command in READ_COMMANDS for _, command in self.registry.commands))
        self.assertEqual("COM6", self.settings.value("light/last_port"))
        self.assertEqual("H", service.state.mode)
        self.assertTrue(all(thread != self.app.thread()
                            for transport in self.registry.transports for thread in transport.open_threads))

    def test_selected_channel_updates_only_that_channel_and_switch_is_read_only(self):
        service = self.service()
        self.connect(service)
        panel = LightPanel(service)
        self.widgets.append(panel)
        before = len(self.registry.commands)
        panel.channel.setCurrentIndex(2)
        self.assertEqual(33, panel.level.value())
        self.assertEqual(before, len(self.registry.commands))
        panel.level.setValue(137)
        self.wait(lambda: service.state.brightness[2] == 137)
        self.assertEqual([31, 32, 137, 34], self.registry.devices["COM6"].values)
        panel.channel.setCurrentIndex(0)
        self.assertEqual(31, panel.level.value())

    def test_dark_adjustment_never_enables_and_off_preserves_levels(self):
        self.registry.devices["COM6"].mode = "L"
        service = self.service()
        self.connect(service)
        service.set_level(2, 120)
        self.wait(lambda: service.state.brightness[1] == 120)
        self.assertEqual("L", service.state.mode)
        self.assertNotIn(b"TH#", [c for _, c in self.registry.commands])
        self.assertTrue(service.enable())
        self.wait(lambda: not service.busy)
        service.off()
        self.wait(lambda: not service.busy)
        self.assertEqual("L", service.state.mode)
        self.assertEqual(120, service.levels[1])
        self.assertEqual(120, service.state.brightness[1])

    def test_pending_levels_are_coalesced_and_off_discards_device_writes(self):
        service = self.service()
        self.connect(service)
        service.set_level(1, 99)
        service.set_level(1, 121)
        self.assertTrue(service.verify_dark())
        self.assertEqual(121, service.levels[0])
        self.assertEqual(31, service.state.brightness[0])
        self.assertNotIn(b"SA0121#", [c for _, c in self.registry.commands])

    def test_live_adjustments_keep_latest_values_for_each_channel_while_busy(self):
        service = self.service()
        self.connect(service)
        self.registry.block_command = b"SA0100#"
        service.set_level(1, 100)
        self.wait(self.registry.started.is_set)
        service.set_level(1, 101)
        service.set_level(1, 102)
        service.set_level(2, 120)
        self.registry.release.set()
        self.wait(lambda: service.state.brightness[:2] == (102, 120))
        self.assertNotIn(b"SA0101#", [c for _, c in self.registry.commands])
        self.assertEqual((102, 120, 33, 34), service.levels)

    def test_disconnect_reconnect_preserves_preferences_and_never_enables(self):
        service = self.service()
        self.connect(service)
        levels = service.levels
        self.assertTrue(service.off(disconnect=True))
        self.wait(lambda: not service.busy)
        self.assertTrue(service._thread.isRunning())
        self.registry.commands.clear()
        self.assertTrue(service.connect_port("COM6"))
        self.wait(lambda: not service.busy)
        self.assertEqual((0, 0, 0, 0), service.state.brightness)
        self.assertEqual(levels, service.levels)
        self.assertTrue(all(c in READ_COMMANDS for _, c in self.registry.commands))

    def test_settings_port_matches_device_selected_by_auto_connection(self):
        self.registry.devices = {"COM7": FakeDevice()}
        service = self.service()
        dialog = LightSettingsDialog(service)
        self.widgets.append(dialog)
        self.assertEqual("COM6", dialog.port.currentData())
        self.connect(service)
        self.assertEqual("COM7", dialog.port.currentData())

    def test_lock_rejects_on_edits_rescan_connect_and_disconnect_but_allows_off(self):
        service = self.service()
        self.connect(service)
        panel = LightPanel(service)
        self.widgets.append(panel)
        service.set_locked("recipe", True)
        self.assertFalse(panel.level.isEnabled())
        self.assertFalse(service.enable())
        self.assertFalse(service.auto_connect())
        self.assertFalse(service.connect_port("COM6"))
        self.assertFalse(service.off(disconnect=True))
        levels = service.levels
        service.set_level(1, 255)
        self.assertEqual(levels, service.levels)
        self.assertTrue(service.verify_dark())
        self.assertEqual("L", service.state.mode)

    def test_failed_off_readback_blocks_start_and_retains_session(self):
        service = self.service()
        self.connect(service)
        self.registry.devices["COM6"].ignore.add(b"TL#")
        host = SimpleNamespace(light_service=service, _on_light_error=Mock())
        self.assertFalse(MainWindow._prepare_light_for_measurement(host, "recipe"))
        self.assertTrue(service.state.shutdown_required)
        self.assertIsNone(service.state.mode)
        host._on_light_error.assert_called_once()
        self.registry.devices["COM6"].ignore.clear()
        self.assertTrue(service.verify_dark())

    def test_close_zeroes_hardware_preserves_saved_values_and_stops_thread(self):
        service = self.service()
        self.connect(service)
        levels = service.levels
        self.assertTrue(service.shutdown())
        self.assertEqual([0, 0, 0, 0], self.registry.devices["COM6"].values)
        self.assertEqual(levels, BrightnessStore(self.root / "light.json").load())
        self.assertFalse(service._thread.isRunning())
        self.assertFalse(service.state.shutdown_required)

    def test_close_failure_keeps_worker_and_allows_retry(self):
        service = self.service()
        self.connect(service)
        self.registry.devices["COM6"].replies[b"SA#"] = b"a0001"
        self.assertFalse(service.shutdown())
        self.assertTrue(service._thread.isRunning())
        self.assertTrue(service.state.shutdown_required)
        self.registry.devices["COM6"].replies.clear()
        self.assertTrue(service.shutdown())

    def test_usb_loss_clears_known_state_and_cannot_switch_to_another_session(self):
        service = self.service()
        self.connect(service)
        service._worker.controller.transport.close()
        service._connection_fault(service._worker.controller.connection_fault())
        self.assertIsNone(service.state.mode)
        self.assertTrue(service.state.shutdown_required)
        self.assertFalse(service.enable())
        self.assertFalse(service.connect_port("COM7"))
        self.assertTrue(service.verify_dark())

    def test_readback_does_not_overwrite_saved_values(self):
        BrightnessStore(self.root / "light.json").save((80, 90, 100, 110))
        service = self.service()
        self.connect(service)
        self.assertEqual((80, 90, 100, 110), service.levels)
        self.registry.devices["COM6"].values = [1, 2, 3, 4]
        self.assertTrue(service.refresh())
        self.wait(lambda: not service.busy)
        self.assertEqual((1, 2, 3, 4), service.state.brightness)
        self.assertEqual((80, 90, 100, 110), service.levels)

    def test_legacy_import_is_once_and_does_not_rewrite_source(self):
        legacy = self.root / "standalone.json"
        BrightnessStore(legacy).save((10, 20, 30, 40))
        original = legacy.read_bytes()
        service = self.service(legacy=legacy)
        self.assertEqual((10, 20, 30, 40), service.levels)
        self.assertEqual(original, legacy.read_bytes())
        BrightnessStore(legacy).save((99, 99, 99, 99))
        second = self.service(legacy=legacy)
        self.assertEqual((10, 20, 30, 40), second.levels)

    def test_settings_failure_still_zeroes_hardware_and_cancels_exit(self):
        service = self.service()
        self.connect(service)
        service.set_level(1, 155)
        with patch.object(service.store, "save", side_effect=OSError("disk full")):
            self.assertFalse(service.shutdown())
        self.assertEqual("L", self.registry.devices["COM6"].mode)
        self.assertEqual([0, 0, 0, 0], self.registry.devices["COM6"].values)
        self.assertTrue(service._thread.isRunning())

    def test_multiple_candidates_require_manual_selection(self):
        self.registry.devices = {"COM7": FakeDevice(), "COM8": FakeDevice()}
        service = self.service()
        self.assertTrue(service.auto_connect())
        self.wait(lambda: not service.busy)
        self.assertFalse(service.state.shutdown_required)
        self.assertEqual("multiple", service.notice)
        self.assertTrue(service.connect_port("COM8"))
        self.wait(lambda: not service.busy)
        self.assertEqual("COM8", service.state.port)

    def test_saved_adapter_serial_follows_changed_com_port(self):
        service = self.service()
        self.settings.setValue("light/last_serial", "COM8-SN")
        with patch("gui.light_service.available_ports", return_value=FakeRegistry({"COM8": FakeDevice()}).ports()):
            self.assertEqual("COM8", service.preferred_port())

    def test_emergency_cancels_enable_before_h_command(self):
        self.registry.devices["COM6"].mode = "L"
        service = self.service()
        self.connect(service)
        self.registry.block_command = b"SA0031#"
        self.assertTrue(service.enable())
        self.wait(self.registry.started.is_set)
        service.set_locked("emergency", True)
        QTimer.singleShot(30, self.registry.release.set)
        self.assertTrue(service.verify_dark(zero=True))
        self.assertNotIn(b"TH#", [c for _, c in self.registry.commands])
        self.assertTrue(service.state.off_confirmed)

    def test_worker_thread_safety_bridge_returns_verified_completion(self):
        service = self.service()
        self.connect(service)
        result = []
        thread = Thread(target=lambda: result.append(service.verify_dark()))
        thread.start()
        self.wait(lambda: bool(result))
        thread.join()
        self.assertEqual([True], result)
        self.assertEqual("L", service.state.mode)

    def test_timeout_cannot_report_success_or_allow_reenable_before_pending_off(self):
        service = self.service()
        self.connect(service)
        self.registry.block_command = b"TL#"
        service.SAFETY_TIMEOUT_MS = 40
        self.assertFalse(service.verify_dark())
        self.assertFalse(service.can_enable)
        self.registry.release.set()
        self.wait(lambda: not service.busy)
        self.assertEqual("L", service.state.mode)

    def test_settings_and_language_switch_share_session_without_commands(self):
        service = self.service()
        self.connect(service)
        panel = LightPanel(service)
        dialog = LightSettingsDialog(service)
        self.widgets.extend((panel, dialog))
        panel.channel.setCurrentIndex(3)
        before = len(self.registry.commands)
        set_language(Language.EN_US, persist=False)
        self.assertEqual("Light Settings", dialog.windowTitle())
        self.assertEqual(4, panel.channel.currentData())
        self.assertEqual("Turn Light Off", panel.power_button.text())
        self.assertEqual(before, len(self.registry.commands))
        dialog.reject()
        self.assertTrue(service.state.connected)
        self.assertTrue(service._thread.isRunning())

    def test_channel_names_persist_and_refresh_without_selection_or_hardware_changes(self):
        service = self.service()
        self.connect(service)
        panel = LightPanel(service)
        dialog = LightSettingsDialog(service)
        self.widgets.extend((panel, dialog))
        panel.channel.setCurrentIndex(1)
        selections = QSignalSpy(panel.channel.currentIndexChanged)
        before = list(self.registry.commands)
        levels = service.levels
        names = ("白光光源", "藍光光源", "紅光光源", "備用")
        for channel, name in enumerate(names, 1):
            edit = dialog.channel_name_edits[channel]
            edit.setText("  " + name + "  ")
            edit.textEdited.emit(edit.text())
            self.assertEqual(name, service.channel_name(channel))
            edit.editingFinished.emit()
            self.assertEqual(name, edit.text())
            self.assertEqual(f"CH{channel}（{name}）", panel.channel.itemText(channel - 1))
        self.assertEqual(2, panel.channel.currentData())
        self.assertEqual(0, selections.count())
        self.assertEqual(before, self.registry.commands)
        self.assertEqual(levels, service.levels)
        self.settings.sync()
        restored_settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        restored = LightService(self.root / "light.json", restored_settings)
        self.services.append(restored)
        self.assertEqual(names, tuple(restored.channel_name(ch) for ch in range(1, 5)))
        set_language(Language.EN_US, persist=False)
        self.assertEqual("CH2 (藍光光源)", panel.channel.currentText())
        self.assertEqual(2, panel.channel.currentData())
        self.assertEqual(0, selections.count())
        dialog.channel_name_edits[2].setText("   ")
        dialog.channel_name_edits[2].editingFinished.emit()
        self.assertEqual("CH2", panel.channel.currentText())
        self.assertEqual(before, self.registry.commands)

    def test_named_channel_still_controls_the_original_physical_channel(self):
        service = self.service()
        self.connect(service)
        panel = LightPanel(service)
        self.widgets.append(panel)
        service.set_channel_name(2, "CH1 藍光光源")
        panel.channel.setCurrentIndex(1)
        self.assertEqual(2, panel.channel.currentData())
        panel.level.setValue(145)
        self.wait(lambda: service.state.brightness[1] == 145)
        self.assertIn(("COM6", b"SB0145#"), self.registry.commands)
        self.assertEqual([31, 145, 33, 34], self.registry.devices["COM6"].values)

    def test_no_device_does_not_block_measurement_or_shutdown(self):
        service = self.service()
        self.assertTrue(service.verify_dark())
        self.assertIsNone(service._thread)
        self.assertTrue(service.shutdown())

    def test_pixel_postprocess_rejects_explicit_light_off_failure(self):
        result = dict(smu_output_off=True, routing_off=True, white_light_off=True,
                      ownership_released=True, ok=True)
        self.assertTrue(verified_safe_shutdown(result))  # Existing archived runs.
        self.assertFalse(verified_safe_shutdown(dict(result, gsp4h_light_off=False)))
        self.assertTrue(verified_safe_shutdown(dict(result, gsp4h_light_off=True)))

    def test_hardware_dark_preparation_requires_light_verification(self):
        control, relay = Mock(), Mock()
        control.ownership = None
        light = Mock()
        light.verify_dark.return_value = False
        adapter = ELMatrixHardwareAdapter(control, relay, Mock(), Mock(), light_service=light)
        with self.assertRaisesRegex(RuntimeError, "GSP4H"):
            adapter.prepare_shared_dark()
        relay.clear_smu_output_channels.assert_not_called()

    def test_main_window_has_one_sidebar_light_panel_and_settings_menu(self):
        with patch("gui.main_window.QSettings", return_value=self.settings), patch(
            "gui.main_window.QStandardPaths.writableLocation", return_value=str(self.root)
        ), patch("gui.main_window.QTimer.singleShot"):
            window = MainWindow()
        try:
            ids = [item.id for item in window.sidebar_registry.items]
            self.assertEqual(1, ids.count("light_control"))
            self.assertEqual(1, ids.count("manual_capture"))
            self.assertIn(window.light_settings_action, window.settings_menu.actions())
            self.assertEqual(4, window.light_panel.channel.count())
            self.assertIs(window.light_panel.service, window.light_service)
        finally:
            window.close()

    def test_emergency_report_waits_for_verified_light_off_before_camera_abort(self):
        service = self.service()
        self.connect(service)
        manager = EmergencyManager(FakeSMUControl(), FakeRelayService())
        manager.light_service = service
        observed = []
        manager.register_abort_action("Camera stop", lambda: observed.append(service.state.off_confirmed))
        report = manager.trigger("manual")
        self.assertTrue(report.actions["GSP4H Light OFF"])
        self.assertEqual([True], observed)

    def test_light_shutdown_failure_does_not_skip_other_emergency_actions(self):
        manager = EmergencyManager(FakeSMUControl(), FakeRelayService())
        manager.light_service = Mock()
        manager.light_service.verify_dark.side_effect = RuntimeError("readback failed")
        callbacks = []
        manager.register_abort_action("Camera stop", lambda: callbacks.append("camera"))
        report = manager.trigger("measurement")
        self.assertFalse(report.actions["GSP4H Light OFF"])
        self.assertTrue(report.actions["SMU OUTPUT OFF"])
        self.assertTrue(report.actions["SMU routing Relays OFF"])
        self.assertEqual(["camera"], callbacks)
        self.assertTrue(any("readback failed" in item for item in report.failures))

    def test_application_close_is_cancelled_on_unverified_light_shutdown(self):
        window, events = close_fixture([True])
        window.light_service = Mock()
        window.light_service.shutdown.return_value = False
        event = FakeCloseEvent()
        with patch("gui.main_window_close.QMessageBox.warning"):
            MainWindow.closeEvent(window, event)
        self.assertFalse(event.accepted)
        self.assertNotIn("RELAY_SHUTDOWN", events)
        window.light_service.shutdown.assert_called_once()

    def test_application_force_exit_also_finishes_light_thread(self):
        window, events = close_fixture([False])
        window._unsafe_smu_close_decision = Mock(return_value="force")
        window._confirm_forced_close = Mock(return_value=True)
        window.light_service = Mock()
        window.light_service.shutdown.return_value = False
        event = FakeCloseEvent()
        with patch("gui.main_window_close.QMessageBox.warning"):
            MainWindow.closeEvent(window, event)
        self.assertFalse(event.accepted)
        self.assertNotIn("SMU_SHUTDOWN:{'force': True}", events)

    def test_emergency_during_dark_verification_does_not_start_measurement(self):
        service = self.service()
        self.connect(service)
        manager = EmergencyManager(FakeSMUControl(), FakeRelayService())
        host = SimpleNamespace(light_service=service, emergency_manager=manager, _on_light_error=Mock())
        self.registry.block_command = b"TL#"
        QTimer.singleShot(10, lambda: manager.trigger("verification"))
        QTimer.singleShot(50, self.registry.release.set)
        self.assertFalse(MainWindow._prepare_light_for_measurement(host, "recipe"))
        self.assertTrue(manager.is_active)


if __name__ == "__main__":
    unittest.main()
