from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.error_reporter import ErrorReporter
from core.i18n import Language, configure_i18n, set_language
from gui.error_center import ErrorCenterDialog
from tests.qt_test_utils import ensure_qapplication


class ErrorCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        configure_i18n(None)
        self.reporter = ErrorReporter()
        self.dialog = ErrorCenterDialog(self.reporter)

    def tearDown(self) -> None:
        self.dialog.close()
        configure_i18n(None)

    def test_search_subsystem_and_severity_filters(self) -> None:
        self.dialog.search_edit.setText("SMU-203")
        self.assertEqual(1, self.dialog.proxy.rowCount())
        self.dialog.search_edit.clear()
        self.dialog.subsystem_combo.setCurrentIndex(self.dialog.subsystem_combo.findData("camera"))
        self.assertGreater(self.dialog.proxy.rowCount(), 0)
        for row in range(self.dialog.proxy.rowCount()):
            definition = self.dialog.proxy.index(row, 0).data(256)
            self.assertEqual("camera", definition.subsystem)
        self.dialog.subsystem_combo.setCurrentIndex(0)
        self.dialog.severity_combo.setCurrentIndex(self.dialog.severity_combo.findData("critical"))
        self.assertGreater(self.dialog.proxy.rowCount(), 0)
        for row in range(self.dialog.proxy.rowCount()):
            definition = self.dialog.proxy.index(row, 0).data(256)
            self.assertEqual("critical", definition.severity.value)

    def test_deep_link_selects_exact_code(self) -> None:
        self.assertTrue(self.dialog.open_code("REL-102"))
        self.assertEqual("REL-102", self.dialog.detail_panel.code_value.text())
        self.assertEqual(0, self.dialog.tabs.currentIndex())

    def test_polarity_measurement_code_is_searchable(self) -> None:
        self.dialog.search_edit.setText("MEAS-202")
        self.assertEqual(1, self.dialog.proxy.rowCount())
        self.assertTrue(self.dialog.open_code("MEAS-202"))
        self.assertEqual("MEAS-202", self.dialog.detail_panel.code_value.text())

    def test_session_history_refresh_and_selection(self) -> None:
        self.reporter.report("CAM-203", present=False)
        self.reporter.report("FILE-201", present=False)
        self.assertEqual(2, self.dialog.history_table.rowCount())
        self.assertEqual("CAM-203", self.dialog.history_table.item(0, 1).text())
        self.dialog._on_history_selected(1, 0, -1, -1)
        self.assertEqual("FILE-201", self.dialog.detail_panel.code_value.text())

    def test_runtime_language_switch_updates_window(self) -> None:
        self.assertEqual("錯誤代碼與故障排除", self.dialog.windowTitle())
        set_language(Language.EN_US, persist=False)
        self.assertEqual("Error Codes & Troubleshooting", self.dialog.windowTitle())


if __name__ == "__main__":
    unittest.main()
