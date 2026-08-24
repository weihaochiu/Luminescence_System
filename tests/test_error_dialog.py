from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.error_reporter import ErrorReporter, format_diagnostics
from core.i18n import Language, configure_i18n, set_language
from gui.dialogs.error_dialog import ErrorDialog
from tests.qt_test_utils import ensure_qapplication


class ErrorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def tearDown(self) -> None:
        configure_i18n(None)

    def _dialog(self, code: str = "SMU-203") -> ErrorDialog:
        event = ErrorReporter().report(
            code,
            context={"channel": "CH1", "command": ":OUTP?", "expected": "OFF", "actual": "UNKNOWN"},
            present=False,
        )
        dialog = ErrorDialog(event)
        self.addCleanup(dialog.close)
        return dialog

    def test_zh_tw_and_en_us_rendering(self) -> None:
        configure_i18n(None)
        dialog = self._dialog()
        self.assertEqual("無法確認 SMU 輸出已關閉", dialog.title_label.text())
        self.assertIn("SMU-203", dialog.code_label.text())
        set_language(Language.EN_US, persist=False)
        self.assertEqual("Unable to Confirm SMU Output OFF", dialog.title_label.text())
        self.assertIn("Error Code: SMU-203", dialog.code_label.text())

    def test_critical_has_context_specific_buttons_and_no_ignore(self) -> None:
        dialog = self._dialog()
        self.assertEqual({"safe_shutdown", "reconnect"}, set(dialog.action_buttons))
        object_names = {button.objectName().casefold() for button in dialog.findChildren(type(dialog.copy_button))}
        self.assertFalse(any("ignore" in name or "continue" in name for name in object_names))

    def test_technical_details_and_copy_diagnostics(self) -> None:
        dialog = self._dialog()
        self.assertFalse(dialog.details_edit.isVisible())
        dialog.toggle_details()
        self.assertFalse(dialog.details_edit.isHidden())
        expected = format_diagnostics(dialog.error_event)
        self.assertEqual(expected, dialog.details_edit.toPlainText())
        dialog.copy_diagnostics()
        self.assertEqual(expected, QApplication.clipboard().text())

    def test_view_details_deep_link_callback_receives_code(self) -> None:
        opened: list[str] = []
        event = ErrorReporter().report("CAM-203", present=False)
        dialog = ErrorDialog(event, error_center_opener=opened.append)
        self.addCleanup(dialog.close)
        dialog.open_error_center()
        self.assertEqual(["CAM-203"], opened)


if __name__ == "__main__":
    unittest.main()
