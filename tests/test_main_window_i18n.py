from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtTest import QSignalSpy

from core.i18n import Language, configure_i18n, set_language
from gui.main_window import MainWindow
from gui.device_panel import DevicePanel
from tests.qt_test_utils import ensure_qapplication


class MainWindowI18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        self.runtime = TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)

    def tearDown(self) -> None:
        configure_i18n(None)

    def _window(self, language: Language) -> MainWindow:
        settings = QSettings(
            str(Path(self.runtime.name) / f"{language.value}.ini"),
            QSettings.Format.IniFormat,
        )
        settings.setValue("ui/language", language.value)
        settings.sync()
        with patch("gui.main_window.QSettings", return_value=settings), patch(
            "gui.main_window.QStandardPaths.writableLocation",
            return_value=self.runtime.name,
        ), patch("gui.main_window.QTimer.singleShot"):
            window = MainWindow()
        self.addCleanup(window.close)
        return window

    def test_zh_tw_and_en_us_startup_translate_representative_main_ui(self) -> None:
        zh = self._window(Language.ZH_TW)
        self.assertIn("檔案", zh.file_menu.title())
        self.assertIn("重新偵測", zh.refresh_action.text())
        self.assertIn("緊急停止", zh.emergency_stop_button.text())
        self.assertEqual("continuous_auto", zh.exposure_mode_combo.itemData(0))
        self.assertIn("相機", zh.sidebar_registry.items[0].display_name)
        self.assertIn("樣品", zh.measurement_control_bar.sample_label.text())
        self.assertIn("未連線", zh.instrument_state_manager.current.status_text)
        zh.close()

        en = self._window(Language.EN_US)
        self.assertIn("File", en.file_menu.title())
        self.assertEqual("Refresh Devices", en.refresh_action.text())
        self.assertIn("Emergency Stop", en.emergency_stop_button.text())
        self.assertEqual("Continuous Auto Exposure", en.exposure_mode_combo.itemText(0))
        self.assertIn("Camera", en.sidebar_registry.items[0].display_name)
        self.assertEqual("Sample Information", en.measurement_control_bar.sample_label.text())
        self.assertEqual("SMU Disconnected", en.instrument_state_manager.current.status_text)

    def test_runtime_round_trip_retranslates_without_combo_side_effect(self) -> None:
        window = self._window(Language.ZH_TW)
        canonical_mode = window.exposure_mode_combo.currentData()
        mode_changes = QSignalSpy(window.exposure_mode_combo.currentIndexChanged)

        set_language(Language.EN_US, persist=False)
        self.app.processEvents()
        self.assertIn("File", window.file_menu.title())
        self.assertEqual("Refresh Devices", window.refresh_action.text())
        self.assertIn("Emergency Stop", window.emergency_stop_button.text())
        self.assertEqual("Continuous Auto Exposure", window.exposure_mode_combo.itemText(0))
        self.assertIn("Camera", window.sidebar_registry.items[0].display_name)
        self.assertEqual("Sample Information", window.measurement_control_bar.sample_label.text())
        self.assertEqual("SMU Disconnected", window.instrument_state_manager.current.status_text)
        self.assertEqual("Camera —", window.camera_status.text())
        self.assertEqual("Image —", window.resolution_status.text())
        self.assertEqual("Exposure —", window.exposure_status.text())
        self.assertEqual("Gain —", window.gain_status.text())
        self.assertEqual("Camera Temperature N/A", window.temperature_status.text())
        self.assertEqual(canonical_mode, window.exposure_mode_combo.currentData())

        set_language(Language.ZH_TW, persist=False)
        self.app.processEvents()
        self.assertIn("檔案", window.file_menu.title())
        self.assertIn("重新偵測", window.refresh_action.text())
        self.assertIn("緊急停止", window.emergency_stop_button.text())
        self.assertIn("持續自動曝光", window.exposure_mode_combo.itemText(0))
        self.assertIn("相機", window.sidebar_registry.items[0].display_name)
        self.assertIn("樣品", window.measurement_control_bar.sample_label.text())
        self.assertIn("未連線", window.instrument_state_manager.current.status_text)
        self.assertIn("相機", window.camera_status.text())
        self.assertIn("影像", window.resolution_status.text())
        self.assertIn("曝光", window.exposure_status.text())
        self.assertIn("相機溫度", window.temperature_status.text())
        self.assertEqual(canonical_mode, window.exposure_mode_combo.currentData())
        self.assertEqual(0, mode_changes.count())

    def test_device_panel_disconnected_and_error_states_retranslate(self) -> None:
        configure_i18n(None)
        panel = DevicePanel()
        self.addCleanup(panel.close)
        panel.set_smu_disconnected(error=True)
        self.assertIn("錯誤", panel.smu_state.text())
        set_language(Language.EN_US, persist=False)
        self.assertEqual("● Error", panel.smu_state.text())
        panel.set_smu_disconnected(error=False)
        self.assertEqual("● Disconnected", panel.smu_state.text())


if __name__ == "__main__":
    unittest.main()
